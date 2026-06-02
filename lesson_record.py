import json

student_name = input("Student Name: ")
lesson_content = input("Lesson Content: ")
performance = input("Performance: ")
homework = input("Homework: ")

lesson_record = {
    "student": student_name,
    "lesson": lesson_content,
    "performance": performance,
    "homework": homework
}

with open("lesson_history.json", "a") as file:
    file.write(json.dumps(lesson_record))
    file.write("\n")

with open("students.json", "r") as file:
    students = json.load(file)

if student_name in students:
    students[student_name]["lessons_left"] -= 1

    with open("students.json", "w") as file:
        json.dump(students, file, indent=4)

    print("\nLesson saved to history!")
    print(f"Remaining lessons: {students[student_name]['lessons_left']}")

    if students[student_name]["lessons_left"] <= 2:
        print("⚠️ Contact parent for renewal.")
else:
    print("\nLesson saved to history!")
    print("Student not found in students.json.")