import random
import os

def get_random_prompt() -> str:
    # Define the path to the file containing the prompts
    prompts_file_path = os.path.join(os.path.dirname(__file__), 'generic.txt')
    
    # Check if the file exists
    if not os.path.exists(prompts_file_path):
        raise FileNotFoundError(f"The prompts file was not found at {prompts_file_path}")
    
    # Read the prompts from the file
    with open(prompts_file_path, 'r') as file:
        prompts = file.readlines()
    
    # Choose a random prompt from the list
    random_prompt = random.choice(prompts).strip()  # strip() removes any leading/trailing whitespace, including newline characters
    
    random_prompt = random.choice(prompts).strip()
    print(f'Random Prompt: {random_prompt}')  # Debugging print statement
    return random_prompt
