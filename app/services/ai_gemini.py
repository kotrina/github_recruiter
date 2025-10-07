# app/services/ai_gemini.py
from app.core.config import settings
import google.generativeai as genai
from typing import Optional, Dict, Any

class GeminiClient:
    def __init__(self, api_key: Optional[str], model_name: str = "gemini-2.5-flash"):
        """
        Inicializa el cliente de Gemini.
        Configura la API y crea una instancia reutilizable del modelo.
        """
        self.api_key = api_key
        self.model = None

        if not api_key:
            print("⚠️ Advertencia: No se proporcionó API key para Gemini.")
            return

        try:
            genai.configure(api_key=api_key)
            # --- MEJORA 1: Crear el modelo una sola vez y reutilizarlo ---
            self.model = genai.GenerativeModel(model_name)
        except Exception as e:
            print(f"❌ Error al configurar el cliente de Gemini: {e}")

    def is_ready(self) -> bool:
        """Comprueba si el cliente está listo para hacer llamadas."""
        return self.model is not None

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_output_tokens: int = 8192,
        top_p: float = 0.9,
        top_k: int = 40,
        safety_settings: Optional[Dict[str, Any]] = None, # --- MEJORA 4: Añadir safety_settings ---
    ) -> dict:
        """
        Devuelve {"text": str} en caso de éxito o {"error": str, "details": ...} en caso de fallo.
        """
        if not self.is_ready():
            return {"error": "El cliente de Gemini no está configurado correctamente."}

        try:
            generation_config = {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "max_output_tokens": max_output_tokens,
            }

            resp = self.model.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=safety_settings, # Pasar la configuración de seguridad
            )
            print("--------------------------")
            print(resp.candidates)
            print("--------------------------")
            # --- MEJORA 2: Manejo detallado de respuestas bloqueadas ---
            if resp.candidates and resp.candidates[0].finish_reason == 'SAFETY':
                return {
                    "error": "Respuesta bloqueada por motivos de seguridad.",
                    "details": {
                        "finish_reason": "SAFETY",
                        "safety_ratings": [str(rating) for rating in resp.candidates[0].safety_ratings],
                    }
                }

            if hasattr(resp, "text") and resp.text:
                return {"text": resp.text}

            # Si no hay texto pero tampoco fue por seguridad, es un caso raro
            return {
                "error": "Respuesta vacía del modelo por una razón desconocida.",
                "details": f"Prompt parts: {resp.prompt_feedback}"
            }

        except Exception as e:
            # --- MEJORA 3: Errores más específicos de la API ---
            # Un error común es 'API key not valid'.
            return {"error": f"Error en la llamada a la API de Gemini: {e}"}


gemini_client = GeminiClient(settings.GEMINI_API_KEY)
