import json
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY"
)


with open("students.json", "r") as file:
    students = json.load(file)


def save_data():
    with open("students.json", "w") as file:
        json.dump(students, file, indent=4)


def deduct_lesson(student):
    if student not in students:
        print("Student not found.")
        return False

    students[student] -= 1
    save_data()

    print(f"{student} finished a lesson.")
    print(f"Remaining lessons: {students[student]}")

    if students[student] <= 2:
        print("⚠️ Contact parent for renewal.")

    print("---------")
    return True


def generate_feedback(student, lesson_notes):
    prompt = f"""
You are a professional piano teacher.

Write a warm and professional parent feedback.

Student:
{student}

Lesson Notes:
{lesson_notes}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


while True:
    student_name = input("Which student finished lesson? ")

    if student_name == "exit":
        print("System closed.")
        break

    lesson_notes = input("Lesson notes: ")

    lesson_recorded = deduct_lesson(student_name)

    if lesson_recorded:
        feedback = generate_feedback(student_name, lesson_notes)
        print(feedback)

        filename = f"{student_name}_feedback.txt"

        with open(filename, "w") as file:
            file.write(feedback)

        print("Feedback saved successfully!")