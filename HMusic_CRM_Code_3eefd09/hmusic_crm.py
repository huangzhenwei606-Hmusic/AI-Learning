print("🏛 H-Music CRM")
print("1. Record Lesson")
print("2. View Student History")
print("3. Generate Parent Email")
print("4. Teacher Dashboard")
print("5. Student Lookup")
print("6. Exit")

choice = input("\nSelect option: ")

if choice == "1":
    exec(open("lesson_record.py").read())

elif choice == "2":
    exec(open("view_history.py").read())

elif choice == "3":
    exec(open("parent_email_generator.py").read())

elif choice == "4":
    exec(open("teacher_dashboard.py").read())

elif choice == "5":
    exec(open("student_lookup.py").read())

elif choice == "6":
    print("System closed.")

else:
    print("Invalid option")