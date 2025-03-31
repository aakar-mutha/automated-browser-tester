from playwright.sync_api import sync_playwright, Playwright

def run(playwright: Playwright):
    chromium = playwright.chromium # or "firefox" or "webkit".
    browser = chromium.launch(headless=False)
    page = browser.new_page()
    try:
        page.goto("https://x.com")
        page.locator("text=Sign in").click()
        page.get_by_label('Phone, email, or username').fill('aakarmutha')
        page.wait_for_timeout(2000)
        page.locator('button:has-text("Next")').click()
        page.wait_for_timeout(2000)
        page.locator('input[name="password"]').fill('a 303jan00')
        page.locator('button:has-text("Log in")').click()
        page.wait_for_timeout(2000)
        page.locator('input[placeholder="Search"]').fill('crustdata')
        page.keyboard.press('Enter')
        page.wait_for_timeout(4000)
        page.get_by_role('article').first.click()
        page.wait_for_timeout(2000)

        

        
        
    except Exception as e:
        print(f"An error occurred: {e}")

with sync_playwright() as playwright:
    run(playwright)