import os
import sys
from google import genai
from dotenv import load_dotenv
from groq import Groq
from errores_groq import *

# 1. Cargar las credenciales del archivo .env
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
model=os.getenv("GROQ_MODEL")

if not api_key and not model:
    print(f"Hay valores None en el env para el modelo, la API o ambos: {e}")  #Comprueba que el valor importado de env no sea None
    sys.exit(1)

client = Groq(api_key=api_key) #se instancia el objecto y gaurda la API key
messages=[]

conection=True
while True:
    try:
        if model not in {m.id for m in client.models.list().data}:
            raise NotFoundError
        if conection:
            print("⏳ Conectando con Gro2q...")
            print("Conexión establecida con Groq")
            conection=False
    except AuthenticationError:
        print("API key incorrecta, caducada o revocada ---> Revisar la API en env")
        sys.exit(1)
    except PermissionDeniedError:
        print("La API key no tiene acceso a este modelo o recurso ---> Revisar permisos en la consola de Groq")
        sys.exit(1)
    except NotFoundError:
        print("El modelo no existe o fue retirado ---> Revisar GROQ_MODEL en env")
        sys.exit(1)



    prompt=input("User:")
    messages.append({"role": "user", "content": prompt})

    if prompt.lower().strip()=="salir":
        print("Fin de la sesión")
        break

    try:
         response = client.chat.completions.create(model=model, messages=messages)
         answer = response.choices[0].message.content
         messages.append({"role": "assistant", "content": answer})
         print(f"Groq: {answer}")
    except BadRequestError:
        print("Petición mal formada (messages vacío o mal formado, role inválido) ---> Revisar messages")
        sys.exit(1)
    except UnprocessableEntityError:
        print("No se puede procesar la petición (contexto demasiado largo) ---> Recortar el historial")
        sys.exit(1)
    except RateLimitError:
        print("Demasiadas peticiones o tokens por minuto ---> Esperar y reintentar")
        sys.exit(1)
    except InternalServerError:
        print("Fallo del servidor de Groq ---> Reintentar más tarde")
        sys.exit(1)
    except APITimeoutError:
        print("La respuesta ha tardado demasiado ---> Reintentar o subir el timeout")
        sys.exit(1)
    except APIConnectionError:
        print("No se pudo conectar con Groq ---> Revisar internet, DNS, firewall o proxy")
        sys.exit(1)
