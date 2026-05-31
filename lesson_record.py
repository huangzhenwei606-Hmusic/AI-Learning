import json
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY"
)

student_name = input("Student Name: ")
lesson_content = input("Today's lesson: ")
performance = input("Performance: ")

lesson = {
    "student": student_name,
    "content": lesson_content,
    "performance": performance
}

with open("lesson_record.json", "w") as file:
    json.dump(lesson, file, indent=4)

prompt = f"""
You are a professional piano teacher.

Write a warm and professional parent feedback based on this lesson record:

Student: {lesson["student"]}
Lesson Content: {lesson["content"]}
Performance: {lesson["performance"]}

Make it easy for parents to understand.
"""

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[
        {"role": "user", "content": prompt}
    ]
)

feedback = response.choices[0].message.content

print(feedback)

with open(f"{student_name}_feedback.txt", "w") as file:
    file.write(feedback)

print("Lesson and feedback saved!")