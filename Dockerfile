# Use a lightweight Python 3.12 image to match your local environment
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your Python files into the container
COPY . .

# Expose port 7860 (Strict requirement for Hugging Face Spaces)
EXPOSE 7860

# Command to run the FastAPI server on the required port
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]