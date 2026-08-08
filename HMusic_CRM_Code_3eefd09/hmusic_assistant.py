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

print("\nLesson Record:")
print(json.dumps(lesson_record, indent=4))

import json

student_name = input("Student Name: ")
lesson_content = input("Lesson Content: ")
performance = input("Performance: ")
homework = input("Homework: ")

lesson_record = {
    "student": student_name,
    "teacher": "Xu Huang",
    "lesson": lesson_content,
    "performance": performance,
    "homework": homework
}

print("\nLesson Record:")
print(json.dumps(lesson_record, indent=4))

with open("lesson_history.json", "a") as file:
    file.write(json.dumps(lesson_record))
    file.write("\n")

print("\nLesson saved to history!")