"""Chat with the agent in your terminal: python chat.py"""
from agent.agent import Agent
from agent.data import fresh_db

if __name__ == "__main__":
    agent = Agent(fresh_db())
    print("Maison Verre client care (type 'quit' to exit)\n")
    while True:
        text = input("You: ").strip()
        if text.lower() in ("quit", "exit"):
            break
        print(f"\nMaison Verre: {agent.reply(text)}\n")
