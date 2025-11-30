FROM python:3.9-slim

# Set Work Directory
WORKDIR /app

# Install Dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy All Files
COPY . .

# Open Port 7860 (Hugging Face Default)
EXPOSE 7860

# Run the Bot
CMD ["python", "main.py"]
