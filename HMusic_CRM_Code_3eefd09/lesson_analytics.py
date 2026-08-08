import json

student_name = input("Student Name: ")

total_lessons = 0

with open("lesson_history.json", "r") as file:
    for line in file:
        lesson = json.loads(line)

        if lesson["student"].lower() == student_name.lower():
            total_lessons += 1

print(f"{student_name} total lessons: {total_lessons}")