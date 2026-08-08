import streamlit as st
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY"
)

st.sidebar.title("H-Music AI System")
st.sidebar.write("AI-powered piano lesson feedback tool")

st.title("H-Music AI Teaching Assistant")

student = st.text_input("Student Name")

learned = st.text_area("What did the student learn today?")

performance = st.text_area("How did the student perform in class?")

improvement = st.text_area("What needs improvement?")

homework = st.text_area("Homework / practice suggestion")

next_goal = st.text_area("Next lesson goal")

if st.button("Generate Feedback"):

    with st.spinner("Generating professional feedback..."):

        prompt = f"""
You are a professional piano teacher.

Write a warm, professional, and parent-friendly lesson feedback.

Student Name:
{student}

What the student learned:
{learned}

Performance in class:
{performance}

Needs improvement:
{improvement}

Homework:
{homework}

Next lesson goal:
{next_goal}

The feedback should:
- sound natural and encouraging
- be easy for parents to understand
- clearly explain progress and next steps
- feel professional but warm
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        feedback = response.choices[0].message.content

        st.divider()
        st.subheader("Generated Feedback")
        st.write(feedback)

        filename = f"{student}_feedback.txt"

        with open(filename, "w") as file:
            file.write(feedback)

        st.success("✅ Feedback generated and saved successfully!")