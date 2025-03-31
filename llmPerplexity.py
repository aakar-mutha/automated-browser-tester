import os
from openai import OpenAI
from dotenv import load_dotenv
from pprint import pprint
load_dotenv()


class llm:
    def __init__(self, system_prompt: str):
        self.model = os.getenv("PERPLEXITY_MODEL")
        self.client = OpenAI(api_key=os.getenv("PERPLEXITY_API_KEY"), base_url=os.getenv("PERPLEXITY_BASE_URL"))
        self.system_prompt = system_prompt
        self.messages = [{"role": "system", "content": self.system_prompt}]
               
    def generate_response(self, user_prompt: str):
        try:
            # Add user message
            self.messages.append({"role": "user", "content": user_prompt})
            
            # Call the API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
            )
            
            # Access response content as object attributes, not dictionary keys
            assistant_message = response.choices[0].message.content
            
            # Add assistant response to message history
            self.messages.append({"role": "assistant", "content": assistant_message})
            
            return assistant_message
        
        except Exception as e:
            print(f"Full error details: {str(e)}")
            return f"Error generating response: {str(e)}"
        

if __name__ == "__main__":
    system_prompt = "You are a helpful assistant."
    user_prompt = "What is the capital of France?"
    
    llm_instance = llm(system_prompt)
    response = llm_instance.generate_response(user_prompt)
    print(response)