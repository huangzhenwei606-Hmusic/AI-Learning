student_name = input("Student Name: ")

lesson = input("Lesson: ")

print("DEBUG LESSON INPUT")

performance = input("Performance: ")

homework = input("Homework: ")

prompt = f"""
You are a professional piano teacher.

Write a parent feedback email.

Student:
{student_name}

Lesson:
{lesson}

Performance:
{performance}

Homework:
{homework}

Keep the tone positive and professional.
"""

print(prompt)