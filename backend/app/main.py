import json
import math
import requests
import uuid
from typing import Dict, Tuple, Optional, List, Any
from datetime import datetime, timedelta

# Framework
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.concurrency import run_in_threadpool

# Geolocalização
from geopy.geocoders import Nominatim
from geopy.distance import great_circle

# =====================================================================
# 1. CONFIGURAÇÃO & BANCO DE DADOS
# =====================================================================

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    PRECO_COMBUSTIVEL: float = Field(default=6.89)
    SALARIO_MOTORISTA: float = Field(default=2500.00)
    VALOR_DIARIA_PADRAO: float = Field(default=150.00, description="Valor pago por dia para alimentação/pernoite")
    DIAS_UTEIS: int = Field(default=22)
    MARGEM_LUCRO: float = Field(default=0.30)
    GEOPY_USER_AGENT: str = "sgl_enterprise_v7_manager"
    OSRM_API_URL: str = "http://router.project-osrm.org/route/v1/driving"

settings = Settings()

# --- BANCO DE DADOS EM MEMÓRIA ---

db_trucks = {
    "vuc-01": {"id": "vuc-01", "nome": "VUC (Veículo Urbano)", "consumo": 6.0, "tanque": 150, "placa": "ABC-1234", "status": "Disponível"},
    "carreta-01": {"id": "carreta-01", "nome": "Carreta LS", "consumo": 2.5, "tanque": 600, "placa": "GHI-9012", "status": "Disponível"},
}

db_drivers = {
    "mot-01": {"id": "mot-01", "nome": "Carlos Silva", "cnh": "1234567890", "foto_url": "https://ui-avatars.com/api/?name=Carlos+Silva&background=0D8ABC&color=fff", "status": "Disponível"},
    "mot-02": {"id": "mot-02", "nome": "Ana Pereira", "cnh": "0987654321", "foto_url": "https://ui-avatars.com/api/?name=Ana+Pereira&background=random", "status": "Disponível"}
}

db_trips = []

# =====================================================================
# 2. MODELOS (SCHEMAS)
# =====================================================================

# --- CAMINHÕES ---
class TruckBase(BaseModel):
    nome: str = Field(..., min_length=2)
    consumo: float
    tanque: int
    placa: str

class TruckCreate(TruckBase):
    pass

class TruckResponse(TruckBase):
    id: str
    status: str

# --- MOTORISTAS ---
class DriverBase(BaseModel):
    nome: str = Field(..., min_length=2)
    cnh: str = Field(..., min_length=5)
    foto_url: Optional[str] = None 

class DriverCreate(DriverBase):
    pass

class DriverResponse(DriverBase):
    id: str
    status: str

# --- CÁLCULO ---
class RouteRequest(BaseModel):
    origem: str
    destino: str
    veiculo_id: str
    ida_e_volta: bool = False
    preco_diesel_personalizado: Optional[float] = None
    valor_diaria_personalizado: Optional[float] = None # NOVO

class FinancialBreakdown(BaseModel):
    custo_combustivel: float
    litros_combustivel: float
    paradas_abastecimento: int
    
    # Novos campos de Motorista
    custo_motorista_salario: float
    custo_motorista_diarias: float
    custo_motorista_total: float
    
    custo_operacional_total: float
    lucro_estimado: float

class RouteResponse(BaseModel):
    distancia_km: float
    tempo_estimado_horas: float
    dias_viagem_estimados: int
    preco_final_frete: float
    detalhes_financeiros: FinancialBreakdown
    route_geometry: Optional[List[List[float]]] = None
    coords_origem: Tuple[float, float]
    coords_destino: Tuple[float, float]
    veiculo_info: dict

# --- RESERVA ---
class TripCreate(BaseModel):
    origem: str
    destino: str
    distancia_km: float
    preco_final: float
    lucro: float
    custo_motorista: float # NOVO: Salva quanto custou o motorista
    veiculo_id: str
    motorista_id: str
    data_inicio: datetime
    paradas_previstas: int = 0

# =====================================================================
# 3. SERVIÇOS
# =====================================================================

class GeoService:
    def __init__(self):
        self.geolocator = Nominatim(user_agent=settings.GEOPY_USER_AGENT)

    async def get_coords(self, city: str) -> Tuple[float, float]:
        location = await run_in_threadpool(self.geolocator.geocode, city, timeout=10)
        if not location:
            raise HTTPException(status_code=404, detail=f"Localização não encontrada: {city}")
        return (location.latitude, location.longitude)

class RoutingService:
    async def get_road_route(self, origin: Tuple[float, float], dest: Tuple[float, float]):
        coords_str = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
        url = f"{settings.OSRM_API_URL}/{coords_str}?overview=full&geometries=geojson"
        try:
            response = await run_in_threadpool(requests.get, url, timeout=10)
            if response.status_code != 200: return None
            data = response.json()
            if data.get("code") != "Ok": return None
            
            route = data["routes"][0]
            raw_coords = route["geometry"]["coordinates"]
            return {
                "dist_km": route["distance"] / 1000,
                "duration_h": route["duration"] / 3600,
                "geometry": [[lat, lon] for lon, lat in raw_coords]
            }
        except:
            return None

# =====================================================================
# 4. LÓGICA DE CONFLITO
# =====================================================================

def check_availability(resource_id: str, start: datetime, end: datetime, resource_type: str = 'veiculo'):
    """Verifica se Veículo ou Motorista já tem viagem nesse período"""
    for trip in db_trips:
        t_start = datetime.fromisoformat(trip['data_inicio'])
        t_end = datetime.fromisoformat(trip['data_fim'])
        
        trip_resource_id = trip['veiculo_id'] if resource_type == 'veiculo' else trip['motorista_id']
        
        if trip_resource_id == resource_id:
            if start < t_end and end > t_start:
                msg = f"{resource_type.capitalize()} já reservado de {t_start.strftime('%d/%m %H:%M')} até {t_end.strftime('%d/%m %H:%M')}"
                return False, msg
    return True, "Disponível"

# =====================================================================
# 5. API ENDPOINTS
# =====================================================================

app = FastAPI(title="SGL Enterprise API V7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

geo_service = GeoService()
routing_service = RoutingService()

# --- MOTORISTAS ---
@app.get("/api/v1/drivers", response_model=List[DriverResponse])
def list_drivers():
    return list(db_drivers.values())

@app.post("/api/v1/drivers", response_model=DriverResponse)
def create_driver(driver: DriverCreate):
    new_id = str(uuid.uuid4())[:8]
    d = driver.dict()
    d["id"] = new_id
    d["status"] = "Disponível"
    if not d.get("foto_url"):
        d["foto_url"] = f"https://ui-avatars.com/api/?name={d['nome'].replace(' ', '+')}&background=random"
    db_drivers[new_id] = d
    return d

@app.delete("/api/v1/drivers/{driver_id}")
def delete_driver(driver_id: str):
    if driver_id in db_drivers:
        del db_drivers[driver_id]
        return {"msg": "Removido"}
    raise HTTPException(404, "Motorista não encontrado")

# --- CAMINHÕES ---
@app.get("/api/v1/trucks", response_model=List[TruckResponse])
def list_trucks():
    return list(db_trucks.values())

@app.post("/api/v1/trucks", response_model=TruckResponse)
def create_truck(truck: TruckCreate):
    new_id = str(uuid.uuid4())[:8]
    new_truck = truck.dict()
    new_truck["id"] = new_id
    new_truck["status"] = "Disponível"
    db_trucks[new_id] = new_truck
    return new_truck

@app.delete("/api/v1/trucks/{truck_id}")
def delete_truck(truck_id: str):
    if truck_id in db_trucks:
        del db_trucks[truck_id]
        return {"msg": "Removido"}
    raise HTTPException(404, "Não encontrado")

# --- VIAGENS & RESERVAS ---
@app.get("/api/v1/trips")
def list_trips():
    trips = sorted(db_trips, key=lambda x: x['data_inicio'], reverse=True)
    enhanced_trips = []
    for t in trips:
        t_copy = t.copy()
        driver = db_drivers.get(t['motorista_id'])
        truck = db_trucks.get(t['veiculo_id'])
        t_copy['motorista_nome'] = driver['nome'] if driver else "Desconhecido"
        t_copy['motorista_foto'] = driver['foto_url'] if driver else ""
        t_copy['veiculo_nome'] = truck['nome'] if truck else "Desconhecido"
        t_copy['veiculo_placa'] = truck['placa'] if truck else "---" 
        enhanced_trips.append(t_copy)
    return enhanced_trips[:20]

@app.post("/api/v1/trips/book")
def book_trip(trip: TripCreate):
    # 1. Calcular Duração
    horas_totais = trip.distancia_km / 70
    dias_necessarios = math.ceil(horas_totais / 8)
    if dias_necessarios < 1: dias_necessarios = 1
    
    data_fim = trip.data_inicio + timedelta(days=dias_necessarios)
    
    # 2. Verificar Conflitos
    truck_ok, truck_msg = check_availability(trip.veiculo_id, trip.data_inicio, data_fim, 'veiculo')
    if not truck_ok: raise HTTPException(status_code=409, detail=f"Conflito: {truck_msg}")

    driver_ok, driver_msg = check_availability(trip.motorista_id, trip.data_inicio, data_fim, 'motorista')
    if not driver_ok: raise HTTPException(status_code=409, detail=f"Conflito: {driver_msg}")

    # 3. Salvar
    trip_data = trip.dict()
    trip_data["id"] = str(uuid.uuid4())[:8]
    trip_data["status"] = "Agendada"
    trip_data["data_inicio"] = trip.data_inicio.isoformat()
    trip_data["data_fim"] = data_fim.isoformat()
    trip_data["dias_duracao"] = dias_necessarios
    
    db_trips.append(trip_data)
    
    if trip.veiculo_id in db_trucks: db_trucks[trip.veiculo_id]["status"] = "Agendado"
    if trip.motorista_id in db_drivers: db_drivers[trip.motorista_id]["status"] = "Agendado"

    return {"msg": "Viagem reservada!", "id": trip_data["id"], "termino_estimado": data_fim}

# --- CÁLCULO ---
@app.post("/api/v1/quote", response_model=RouteResponse)
async def calculate_quote(payload: RouteRequest):
    if payload.veiculo_id not in db_trucks:
        raise HTTPException(status_code=400, detail="Veículo não encontrado.")
    
    vehicle_data = db_trucks[payload.veiculo_id]
    
    try:
        c_origem = await geo_service.get_coords(payload.origem)
        c_destino = await geo_service.get_coords(payload.destino)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    route_data = await routing_service.get_road_route(c_origem, c_destino)
    
    if route_data:
        distancia_km = route_data["dist_km"]
        tempo_horas = route_data["duration_h"]
        geometry = route_data["geometry"]
    else:
        distancia_km = great_circle(c_origem, c_destino).km * 1.2 
        tempo_horas = distancia_km / 70
        geometry = None

    if payload.ida_e_volta:
        distancia_km *= 2
        tempo_horas *= 2

    dias_viagem = max(1, math.ceil(tempo_horas / 8))

    litros_total = distancia_km / vehicle_data["consumo"]
    tanque = vehicle_data["tanque"]
    paradas = math.ceil((litros_total - tanque) / tanque) if litros_total > tanque else 0

    preco_diesel = payload.preco_diesel_personalizado or settings.PRECO_COMBUSTIVEL
    valor_diaria = payload.valor_diaria_personalizado if payload.valor_diaria_personalizado is not None else settings.VALOR_DIARIA_PADRAO

    # Custos
    custo_combustivel = litros_total * preco_diesel
    
    # Custo Motorista = (Salario / Dias Uteis * Dias Viagem) + (Diaria * Dias Viagem)
    custo_salario_proporcional = (settings.SALARIO_MOTORISTA / settings.DIAS_UTEIS) * dias_viagem
    custo_diarias = valor_diaria * dias_viagem
    custo_motorista_total = custo_salario_proporcional + custo_diarias

    custo_total = custo_combustivel + custo_motorista_total
    preco_venda = custo_total / (1 - settings.MARGEM_LUCRO)
    lucro = preco_venda - custo_total

    return RouteResponse(
        distancia_km=round(distancia_km, 2),
        tempo_estimado_horas=round(tempo_horas, 1),
        dias_viagem_estimados=dias_viagem,
        preco_final_frete=round(preco_venda, 2),
        route_geometry=geometry,
        coords_origem=c_origem,
        coords_destino=c_destino,
        veiculo_info=vehicle_data,
        detalhes_financeiros=FinancialBreakdown(
            custo_combustivel=round(custo_combustivel, 2),
            litros_combustivel=round(litros_total, 2),
            paradas_abastecimento=paradas,
            custo_motorista_salario=round(custo_salario_proporcional, 2), # NOVO
            custo_motorista_diarias=round(custo_diarias, 2), # NOVO
            custo_motorista_total=round(custo_motorista_total, 2), # NOVO
            custo_fixo_diario=round(custo_salario_proporcional, 2), # Mantido para compatibilidade
            custo_operacional_total=round(custo_total, 2),
            lucro_estimado=round(lucro, 2)
        )
    )