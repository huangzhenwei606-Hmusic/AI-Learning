student_name = input("Student Name: ")
lesson = input("Lesson: ")
performance = input("Performance: ")
homework = input("Homework: ")

email = f"""
Dear Parents,

{student_name} had a {performance.lower()} lesson today.

During today's lesson, we worked on:

{lesson}

Homework for this week:

{homework}

Thank you for your support.

Warm regards,
H-Music
"""

with open(f"{student_name}_parent_email.txt", "w") as file:
    file.write(email)

print(email)

print("\nParent email saved!")