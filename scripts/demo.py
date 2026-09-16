"""Simple Demo App - LocalMind Demo""" 
import random 
 
def main(): 
    print("=" * 40) 
    print("  Welcome to LocalMind Demo App!") 
    print("=" * 40) 
    name = input("\nWhat's your name? ").strip() or "Friend" 
    fortunes = [ 
        "Great day ahead!", "Good luck coming!", "Surprise incoming!", 
        "Hard work pays off!", "Someone thinks of you!", "Perfect day for new things!" 
    ] 
    print(f"\nFortune: {random.choice(fortunes)}")
    target = random.randint(1, 10) 
    while attempts: 
        g = input(f"Guess 1-10 ({attempts} left): ") 
        try: 
            if int(g) == target: print("You win!"); break 
            print("Too low!" if int(g) < target else "Too high!" if int(g) > target else "") 
            attempts -= 1
        except: print("Invalid") 
    if not attempts: print(f"The number was {target}") 
    print(f"Thanks, {name}!") 
if __name__ == "__main__": main()
