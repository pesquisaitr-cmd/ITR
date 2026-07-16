# Usar imagem base do Python
FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Copiar todos os arquivos do repositório para o container
COPY . /app

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Expor a porta usada pelo Streamlit
EXPOSE 8080

# Comando para rodar o dashboard
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
