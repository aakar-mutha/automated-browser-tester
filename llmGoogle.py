import os
from google import genai
from dotenv import load_dotenv
from pprint import pprint
load_dotenv()


class llm:
    def __init__(self, system_prompt: str):
        # self.config = GenerateContentConfigOrDict(system_instruction = system_prompt)
        self.model = os.getenv("GEMINI_MODEL")
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.system_prompt = system_prompt
        self.chat = self.client.chats.create(model=self.model)
        self.chat.send_message(self.system_prompt)
        
    def generate_response(self, user_prompt: str):
        try:
            response = self.chat.send_message(user_prompt)
            # print(f"Response: {response}")
            return response.text
        except Exception as e:
            return f"Error generating response: {str(e)}"
        

if __name__ == "__main__":
    system_prompt = "You are a helpful assistant."
    user_prompt = "What is the capital of France?"
    
    llm_instance = llm(system_prompt)
    response = llm_instance.generate_response(user_prompt)
    print(response)