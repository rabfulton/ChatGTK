import requests
from typing import Optional

class WolframService:
    """Service for interacting with the Wolfram Alpha LLM API."""

    def __init__(self):
        self.base_url = "https://www.wolframalpha.com/api/v1/llm-api"

    def query(self, input_text: str, app_id: str) -> str:
        """
        Query the Wolfram Alpha LLM API.

        Args:
            input_text: The user's query.
            app_id: The Wolfram Alpha App ID.

        Returns:
            The text result from Wolfram Alpha or an error message.
        """
        if not app_id:
            return "Error: Wolfram Alpha App ID is not configured."

        params = {
            "appid": app_id,
            "input": input_text
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.text
            elif response.status_code == 400:
                return f"Error: Bad request (400). Check your input or App ID."
            elif response.status_code == 403:
                return f"Error: Forbidden (403). Check your App ID permissions."
            elif response.status_code == 501:
                return f"Error: Not implemented (501). The query could not be processed."
            else:
                return f"Error: Wolfram Alpha API returned status {response.status_code}: {response.text}"
                
        except requests.RequestException as e:
            return f"Error calling Wolfram Alpha API: {e}"
