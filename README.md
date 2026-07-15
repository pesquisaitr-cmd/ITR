# Dashboard ITR

Repositório para versionamento e deploy do **Dashboard ITR (Imposto Territorial Rural)**.  
Este projeto utiliza **Python + Streamlit** para gerar visualizações interativas a partir das bases governamentais de ITR.

---

## 📂 Estrutura do Projeto
- `app.py` → código principal do dashboard  
- `requirements.txt` → dependências Python  
- `Dockerfile` → configuração do container  
- `cloudbuild.yaml` → pipeline de build e deploy no GCP  
- `dados/` → arquivos de dados (se aplicável)

---

## 🚀 Como rodar localmente
1. Clone o repositório:
   ```bash
   git clone https://github.com/pesquisaitr-cmd/ITR.git
   cd ITR
