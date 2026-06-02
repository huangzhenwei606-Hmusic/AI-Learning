import json

student_name = input("Student Name: ")

with open("students.json", "r") as file:
    students = json.load(file)

total_lessons = 0

with open("lesson_history.json", "r") as file:
    for line in file:
        lesson = json.loads(line)

        if lesson["student"].lower() == student_name.lower():
            total_lessons += 1

if student_name in students:
    print("\nStudent Lookup")
    print("----------------")
    print("Student:", student_name)
    print("Teacher:", students[student_name]["teacher"])
    print("Instrument:", students[student_name]["instrument"])
    print("Lessons Left:", students[student_name]["lessons_left"])
    print("Total Lessons Taken:", total_lessons)
else:
    print("Student not found.")