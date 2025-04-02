from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
import uvicorn
import llmGoogle
import uuid
from typing import Dict

# Session state management
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}
    
    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "page": None,
            "commands_executed": [],
            "retry_count": 0,
            "page_content": ""
        }
        return session_id
    
    async def get_page(self, session_id: str, browser):
        if session_id not in self.sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if not self.sessions[session_id]["page"]:
            self.sessions[session_id]["page"] = await browser.new_page()
        
        return self.sessions[session_id]["page"]

session_manager = SessionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser, _llm
    async with async_playwright() as playwright:
        _browser = await playwright.chromium.launch(headless=False)
        _llm = llmGoogle.llm()
        yield
        await _browser.close()

app = FastAPI(lifespan=lifespan)
_browser, _llm = None, None

@app.post("/start_session")
async def start_session():
    return {"session_id": session_manager.create_session()}

@app.post("/interact/{session_id}")
async def interact_command(session_id: str, command: dict):
    global _browser
    
    if session_id not in session_manager.sessions:
        raise HTTPException(status_code=404, detail="Invalid session ID")
    
    session = session_manager.sessions[session_id]
    page = await session_manager.get_page(session_id, _browser)
    
    # Update page content
    session["page_content"] = await page.content()
    
    system_prompt = f"""
    **Session Context**
    Previous Commands: {session['commands_executed'][-3:]}
    Current Page Content: {session['page_content'][:2000]}...
    Errors Encountered: {session.get('last_error', 'None')}
    
    **Command Rules**
    1. Generate ONLY ONE Playwright command
    2. Handle element existence checks inline
    3. Use explicit timeouts (5000ms minimum)
    4. Prioritize data-testid selectors
    5. Include necessary waits
    """
    
    response = _llm.generate_response(
        system_prompt, 
        command.get("message", "")
    )
    
    try:
        command_line = next(line.strip() for line in response.split("\n") if line.strip())
        if "await" in command_line:
            command_line = command_line.replace("await", "").strip()
        
        # Safe execution with context
        exec_globals = {"page": page}
        await eval(command_line, exec_globals)
        
        session["commands_executed"].append(command_line)
        session["retry_count"] = 0
        return {
            "status": "continue",
            "command": command_line,
            "remaining_steps": len(session["commands_executed"]) % 3  # Example condition
        }
    
    except Exception as e:
        session["retry_count"] += 1
        session["last_error"] = str(e)
        
        if session["retry_count"] >= 3:
            await page.close()
            del session_manager.sessions[session_id]
            return {
                "status": "failed",
                "error": f"Max retries exceeded: {str(e)}"
            }
        
        return {
            "status": "retry",
            "error": str(e),
            "retries_left": 3 - session["retry_count"]
        }

@app.post("/end_session/{session_id}")
async def end_session(session_id: str):
    if session_id in session_manager.sessions:
        await session_manager.sessions[session_id]["page"].close()
        del session_manager.sessions[session_id]
    return {"status": "session closed"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
