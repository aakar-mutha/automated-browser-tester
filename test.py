from fastapi import FastAPI
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
import uvicorn
from llmGoogle import llm
import uuid

# system_prompt_for_interact = """
#     **Role**  
#     Playwright Python command generator for active browser sessions

#     **Input Format**  
#     Natural language instruction (e.g., "Take screenshot of header after login")

#     **Output Rules**  
#     1. EXCLUSIVELY output a SINGLE async Playwright Python command using the existing `page` object and the next input command on a new line.
#     2. "<command> \n <next_input_command>"
#     3. No explanations, comments, or formatting symbols
#     4. Always start by navigating to the page that we want.
#     5. Prioritize these methods:
#         - role-based locators (get_by_role)
#         - text-based locators (get_by_text)
#     6. Include essential waits:
#         - wait_for_timeout(2000) for fixed delays
#         - wait_for_load_state("networkidle")
#         - wait_for_selector() with 10s timeout
#     7. Chain related actions using:  
#         .first  
#         .nth(index)  
#         .filter() 
#     8. Check if the element exists before clicking or filling using:
#         - if locator.count() > 0:  
#         - if locator.is_visible():
#         - if locator.is_hidden():
#         - if locator.is_enabled():               
#     9. Replace <variable_value> with the actual value in the command.
#     10. If an input is involved, check if the input field is properly filled before submitting.
    
    
#     **Examples**
#     1. 
#     Input: "log in into https://practicetestautomation.com/practice-test-login/ with username student and password Password123"
#     Output: "await page.goto("https://practicetestautomation.com/practice-test-login/") \n Fill out the username field with 'student'."
    
#     Input: "Fill out the username field with 'student'."
#     Output: "await page.get_by_role('textbox', name='Username').fill('student') \n Wait for the password field to be visible. If already visible, continue."
    
#     Input: "Fill in the password field with Password123."
#     Output: "await page.get_by_role('textbox', name='Password').fill('Password123') \n Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
    
#     Input: "Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
#     Output: "await page.get_by_role('button', name='Submit').click() \n print('#completed')"
    
#     Input: "Set action_done to True."
#     Output: "print('#completed') \n Done."
    
    
#     2. 
#     Input: "log in into reddit.com with username boogiemann and password Aakar@2000"
#     Output: "await page.goto('https://reddit.com') \n Verify that the Reddit homepage has loaded."

#     Input: "Verify that the Reddit homepage has loaded."
#     Output: "await page.get_by_role('link', name='Log In').wait_for(timeout=5000) \n Locate the 'Log In' link."

#     Input: "Locate the 'Log In' link."
#     Output: "await page.get_by_role('link', name='Log In').click() \n Wait for the username field to become visible."

#     Input: "Wait for the username field to become visible."
#     Output: "await page.get_by_role('textbox', name='Username').wait_for(timeout=5000) \n Fill in the username field with 'boggiemann'."

#     Input: "Fill in the username field with 'boggiemann'."
#     Output: "await page.get_by_role('textbox', name='Username').fill('boggiemann') \n Wait for the password field to become visible."

#     Input: "Wait for the password field to become visible."
#     Output: "await page.get_by_role('textbox', name='Password').wait_for(timeout=5000) \n Fill in the password field with 'Aakar@2000'."

#     Input: "Fill in the password field with 'Aakar@2000'."
#     Output: "await page.get_by_role('textbox', name='Password').fill('Aakar@2000') \n Wait a moment before submitting."

#     Input: "Wait a moment before submitting."
#     Output: "await page.wait_for_timeout(1000) \n Click the 'Log In' button."

#     Input: "Click the 'Log In' button."
#     Output: "await page.get_by_role('button', name='Log In').click() \n Wait a moment after submitting."

#     Input: "Wait a moment after submitting."
#     Output: "await page.wait_for_timeout(1000) \n Navigate to Popular."

#     Input: "Navigate to Popular."
#     Output: "await page.locator('a:has-text(\"Popular\")').click() \n Wait for the 'Popular' page to load."

#     Input: "Wait for the 'Popular' page to load."
#     Output: "await page.wait_for_load_state('networkidle') \n Set action_done to True."
    
#     Input: "Set action_done to True."
#     Output: "print('#completed') \n Done."
# """


system_prompt_for_interact = """
    *`*Role**  
    You are an expert UI tester working in Playwright Python. Your task is to generate commands for the active browser tab.

    **Input Format**  
    Natural language instruction (e.g., "Take screenshot of header after login").

    **Output Rules**  
    1. EXCLUSIVELY output a SINGLE async Playwright Python command using the existing `page` object followed by the next input command on a new line.
    2. Format: `<command> \n <next_input>`
    3. DO NOT USE MARKDOWN CODE BLOCKS. DO NOT USE TRIPLE BACKTICKS (```). Output raw commands only 1 step at a time.
    4. No explanations, comments, or formatting symbols. Strictly follow the format.
    5. ALWAYS start by navigating to the desired page using `await page.goto(<URL>)`.
    6. Prioritize the following locator methods:
        - role-based locators (e.g., `get_by_role`)
        - text-based locators (e.g., `get_by_text`)
    7. Ensure proper waits:
        - `wait_for_timeout(2000)` for fixed delays
        - `wait_for_load_state("networkidle")`
        - `wait_for_selector()` with a 2s timeout
    8. Chain related actions using:
        - `.first()`
        - `.nth(index)`
        - `.filter()`
    9. Check if elements exist before interacting:
        - `if locator.count() > 0:`
        - `if locator.is_visible():`
        - `if locator.is_enabled():`
    10. Replace `<variable_value>` with the actual value in the command.
    11. If an input is involved, confirm that the field is filled before submitting.

    **Examples**

    1. 
    Input: "log in into https://practicetestautomation.com/practice-test-login/ with username student and password Password123"
    Output: "await page.goto("https://practicetestautomation.com/practice-test-login/") \n Fill out the username field with 'student'."
    
    Input: "Fill out the username field with 'student'."
    Output: "await page.get_by_role('textbox', name='Username').fill('student') \n Wait for the password field to be visible. If already visible, continue."
    
    Input: "Fill in the password field with Password123."
    Output: "await page.get_by_role('textbox', name='Password').fill('Password123') \n Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
    
    Input: "Wait for the submit button to be enabled/ If already enabled, click on the submit/log in button."
    Output: "await page.get_by_role('button', name='Submit').click() \n print('#completed')"
    
    Input: "Set action_done to True."
    Output: "print('#completed') \n Done."


    2.  
    Input: "log in into reddit.com with username boogiemann and password Aakar@2000 and navigate to popular"
    Output: "await page.goto('https://reddit.com') \n Verify that the Reddit homepage has loaded."

    Input: "Verify that the Reddit homepage has loaded."
    Output: "await page.get_by_role('link', name='Log In').wait_for(timeout=5000) \n Locate the 'Log In' link."

    Input: "Locate the 'Log In' link."
    Output: "await page.get_by_role('link', name='Log In').click() \n Wait for the username field to become visible."

    Input: "Wait for the username field to become visible."
    Output: "await page.get_by_role('textbox', name='Username').wait_for(timeout=5000) \n Fill in the username field with 'boggiemann'."

    Input: "Fill in the username field with 'boggiemann'."
    Output: "await page.get_by_role('textbox', name='Username').fill('boggiemann') \n Wait for the password field to become visible."

    Input: "Wait for the password field to become visible."
    Output: "await page.get_by_role('textbox', name='Password').wait_for(timeout=5000) \n Fill in the password field with 'Aakar@2000'."

    Input: "Fill in the password field with 'Aakar@2000'."
    Output: "await page.get_by_role('textbox', name='Password').fill('Aakar@2000') \n Wait a moment before submitting."

    Input: "Wait a moment before submitting."
    Output: "await page.wait_for_timeout(1000) \n Click the 'Log In' button."

    Input: "Click the 'Log In' button."
    Output: "await page.get_by_role('button', name='Log In').click() \n Wait a moment after submitting."

    Input: "Wait a moment after submitting."
    Output: "await page.wait_for_timeout(1000) \n Navigate to Popular."

    Input: "Navigate to Popular."
    Output: "await page.locator('a:has-text(\"Popular\")').click() \n Wait for the 'Popular' page to load."

    Input: "Wait for the 'Popular' page to load."
    Output: "await page.wait_for_load_state('networkidle') \n Set action_done to True."
    
    Input: "Set action_done to True."
    Output: "print('#completed') \n Done."
    """
MAX_RETRIES = 5

class SessionManager:
    """Manages browser sessions."""
    def __init__(self):
        self.sessions = dict()

    def create_session(self):
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "page": None,
            "commands_executed": [],
            "page_content": "",
            "retry_count": 0,
            "action_done": False,
            "llm": None,
            "last_command": None,
        }
        return session_id
    
    def get_session(self, session_id):
        if session_id not in self.sessions:
            return None
        return self.sessions.get(session_id, None)
    
    
session_manager = SessionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the FastAPI app."""
    global _browser, _llm
    async with async_playwright() as playwright:
        _browser = await playwright.chromium.launch(headless=False)
        yield
        await _browser.close()
    
app = FastAPI(lifespan=lifespan)

_browser, _llm = None, None

@app.post("/start_session")
async def start_session(mode:str = "interact"):
    """Creates a new browser session."""
    session_id = session_manager.create_session()
    if mode.strip().lower() == "interact":
        session_manager.sessions[session_id]["llm"] = llm(system_prompt_for_interact)
    return {"session_id": session_id}

@app.post("/interact/{session_id}")
async def interact_command(session_id: str, command: dict):
    
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Invalid session ID", "status": "failure", "code": 400}
    
    if not session["page"]:
        session["page"] = await _browser.new_page()
    
    page = session["page"]
    user_message = command.get("message", None)
    
    if not user_message:
        return {"error": "No message provided", "status": "failure", "code": 400}

    goal = user_message
    while not session['action_done'] and session['retry_count'] < MAX_RETRIES:
        try:
            response = session["llm"].generate_response(user_message)
            print(response)
            # Pick only the first non-empty command
            command_line, next_command  = [line.strip() for line in response.split("\n") if line.strip()]
            if "await" in command_line:
                command_line = command_line.replace("await", "").strip()
                
            elif "#completed" in command_line:
                session['action_done'] = True
                break   
            
            # print(command_line)
            session["last_command"] = command_line
            
            await eval(command_line)
            # await page.wait_for_timeout(5000)
            # if "click" in command_line:
                # await page.wait_for_load_state("networkidle")
                # await page.wait_for_timeout(3000)
            # await page.wait_for_timeout(500)
            session['commands_executed'].append(command_line)
            page_content = await page.evaluate("document.body.innerHTML")
            page_content = page_content.replace("\n", " ").replace("\r", " ").replace("\t", " ").replace("  ", " ")
            session['page_content'] = page_content
            user_message = "**Final Goal**\n" + goal
            user_message += f"\n\n**Current Page Content**\n{page_content[:2000]}"
            user_message += f"\n\n **Next Goal**\n{next_command}"      
            
            user_message += f"\n\n**Commands Executed**\n{"\n".join(session['commands_executed'])}"      
            session['retry_count'] = 0
                        
        except Exception as e:
            session['retry_count'] += 1
            
            if session['retry_count'] >= MAX_RETRIES:
                return {"status": "failure", "error": f"{e}", "commands_executed": session['commands_executed']}
            # print(f"Error: {e}")
            # user_message = f"\n\n**Error**\n The type of element might not be found. Following is the error\n{e}. Use a different attribute or locator to find the element."
            # user_message += f"\n\n**Current Page Content**\n{session['page_content']}"
            # user_message += f"\n\n**Last Executed Command**\n{session["last_command"]}"
            
            user_message = f"The command '{session.get('last_command', '')}' failed with error: {e}. Please try a different approach."
            user_message += f"\n\n**Current Page Content**\n{session['page_content']}"
            user_message += f"\n\n**Commands Executed**\n{"\n".join(session['commands_executed'])}"
            

        if session['retry_count'] >= MAX_RETRIES:
            session['action_done'] = False
            return {"status": "failure", "commands_executed": session['commands_executed'], "error": "Max retries reached", "code": 500}

        if session['action_done']:
            break
        
    return {"status": "success", "commands_executed": session['commands_executed'], "code": 200}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
