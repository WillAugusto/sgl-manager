🚛 SGL Manager - Sistema de Gestão Logística

Sistema completo de ERP para logística e cálculo de fretes, desenvolvido para gerenciar frotas, motoristas e orçamentos de viagens.

🚀 Funcionalidades (Versão 7.0)

Calculadora de Frete Inteligente:

Cálculo automático com base na distância (OSRM) e consumo do veículo.

Considera custos de combustível, salário do motorista e diárias.

Visualização de rota interativa no mapa.

Gestão de Frota: Cadastro e controle de status de caminhões.

Gestão de Motoristas: Cadastro de pilotos com fotos e verificação de agenda.

Cronograma: Agendamento de viagens com validação de conflitos de data.

🛠️ Tecnologias Utilizadas

Backend: Python, FastAPI, Pydantic, Geopy.

Frontend: HTML5, Tailwind CSS, Leaflet.js (Mapas), Lucide Icons.

Roteirização: OSRM (Open Source Routing Machine).

📦 Como Rodar o Projeto

1. Backend (API)

Certifique-se de ter o Python instalado.

cd backend
python -m venv .venv
# Ative o ambiente virtual (Windows: .\.venv\Scripts\activate | Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload


2. Frontend (Interface)

Basta abrir o arquivo frontend/index.html no seu navegador.
Para melhor experiência, utilize a extensão "Live Server" do VS Code.

Desenvolvido como projeto de portfólio.