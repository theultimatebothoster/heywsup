import subprocess
import sys

def run_script(script_name):
    return subprocess.Popen([sys.executable, script_name])

if __name__ == "__main__":
    print("🚀 Starting FastAPI Web Dashboard and Discord Bot concurrently...")
    
    # Start the web dashboard (FastAPI)
    web_process = run_script("nexus_dashboard.py")
    
    # Start the Discord bot
    bot_process = run_script("bot.py")
    
    try:
        web_process.wait()
        bot_process.wait()
    except KeyboardInterrupt:
        web_process.terminate()
        bot_process.terminate()
        print("🛑 Shutting down services.")