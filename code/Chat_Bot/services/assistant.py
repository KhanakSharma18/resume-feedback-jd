import os
import webbrowser
from . import musicLibrary
from .news_api import fetch_random_news as news
from .llama_test import query_model as response
# def AI(query: str) -> str:
#     """Send query to Gemini AI and return response."""
#     response = model.generate_content(query + "\nPlease provide a short reply.")
#     return response.text

def process_command(command: str, pdf_text: str = None) -> str:
    """Process user command and return response text. If pdf_text is provided, use it for context."""
    try:
        c = command.lower()

        if "open google" in c:
            webbrowser.open("https://google.com")
            return "Opening Google..."
        elif "open youtube" in c:
            webbrowser.open("https://youtube.com")
            return "Opening YouTube..."
        elif "news" in c:
            key = os.environ.get("NEWS_API_KEY")
            if not key:
                return "News is off: set the NEWS_API_KEY environment variable."
            return news(key, country="us")
        elif c.startswith("play"):
            song = c.split(" ")[1]
            link = musicLibrary.music.get(song)
            if link:
                webbrowser.open(link)
                return f"Playing {song}..."
            else:
                return "Song not found."
        else:
            if pdf_text:
                # Pass the PDF text as context to the model
                prompt = f"Based on the following PDF content, answer the user's question.\nPDF Content:\n{pdf_text}\n\nUser Question: {command}"
                return response(prompt)
            else:
                return response(command)

    except Exception as e:
        return f"Error: {e}"
