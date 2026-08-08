from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY"
)

student = input("Student Name: ")

notes = input("Lesson Notes: ")

prompt = f"""
You are a professional piano teacher.

Based on the lesson notes below, write a warm, clear, and professional parent feedback.

Student Name:
{notes}

Lesson Notes:
{notes}

The feedback should include:
1. What the student learned today
2. How the student performed in class
3. What needs improvement
4. Homework suggestion
5. Encouraging closing sentence

Write it in a friendly tone for parents.
"""

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[
        {"role": "user", "content": prompt}
    ]
)

feedback = response.choices[0].message.content

print(feedback)

filename = f"{student}_feedback.txt"

with open(filename, "w") as file:
    file.write(feedback)

print("Feedback saved successfully!")