students = [
    {
        "name": "Emma",
        "parent": "Siying",
        "teacher": "Ms. Mia",
        "remaining_lessons": 10
    },
    {
        "name": "Tom",
        "parent": "David",
        "teacher": "Mr. Jack",
        "remaining_lessons": 3
    }
]

for student in students:

    student["remaining_lessons"] -= 1

    print("Student:", student["name"])
    print("Parent:", student["parent"])
    print("Teacher:", student["teacher"])
    print("Remaining lessons:", student["remaining_lessons"])

    if student["remaining_lessons"] <= 2:
        print("⚠️ Internal Reminder: Contact parent for renewal.")

    print("------")