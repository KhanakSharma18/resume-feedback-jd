"""
Client for the Llama 3.1 model that runs in Google Colab (see code/notebook/).

The Colab notebook prints a public URL every time it starts. Give it to the app with an environment variable:
    Windows PowerShell:  $env:LLAMA_API_URL = "https://xxxx.trycloudflare.com/query"
    macOS / Linux:       export LLAMA_API_URL="https://xxxx.trycloudflare.com/query"
"""
import json
import os

import requests

CONCISE_SUFFIX = " keep the answer short and precise"   # appended to every prompt unless concise=False


def query_model(text_prompt, url=None, system=None, temperature=None, concise=True):
    """
    Sends a prompt to the Colab API and returns the model's text.
      system       optional system prompt (the notebook has a default one)
      temperature  optional sampling temperature, e.g. 0.2 (the notebook default is 0.6)
      concise      keep the old behaviour of adding "keep the answer short and precise"
    Returns "Model error: ..." text if the model cannot be reached.
    """
    url = url or os.environ.get("LLAMA_API_URL", "").strip()
    if not url:
        return "Model error: LLAMA_API_URL is not set. Start the Colab notebook and set it to the URL it prints (ending in /query)."

    payload = {"prompt": text_prompt + (CONCISE_SUFFIX if concise else "")}
    if system is not None:
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature

    try:
        # long resumes need more than 30 seconds
        response = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=300)
        response.raise_for_status()
        return response.json().get("response", "No 'response' key found in the JSON data.")
    except requests.exceptions.RequestException as e:
        return f"Model error: {e}"
    except (json.JSONDecodeError, ValueError):
        return "Model error: the server sent a reply I couldn't read."


if __name__ == "__main__":
    print(query_model("What are the three most famous landmarks in Agra?"))
