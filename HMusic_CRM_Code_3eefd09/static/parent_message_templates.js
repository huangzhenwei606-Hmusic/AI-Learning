/* Editable English drafts only: selecting a template never sends a message. */
(function(root) {
  'use strict';
  const options = [
    ['custom','Custom message'],
    ['reminder','Lesson reminder'],
    ['confirmation','Schedule confirmation'],
    ['attendance','Attendance check'],
    ['reschedule','Rescheduling request'],
    ['followup','Lesson follow-up']
  ];
  function build(kind, lesson, parent) {
    if(kind === 'custom') return '';
    const name=parent.student || lesson.student || 'your child';
    const greeting=`Hi ${parent.name || 'there'},`;
    const day=new Date(lesson.date+'T12:00:00');
    const date=Number.isNaN(day.getTime())?lesson.date:new Intl.DateTimeFormat('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'}).format(day);
    const details=[`Student: ${name}`,`Date: ${date}`,`Time: ${lesson.display_time || lesson.time} (Pacific Time)`,lesson.teacher?`Teacher: ${lesson.teacher}`:'',lesson.duration?`Duration: ${lesson.duration} minutes`:'',lesson.location?`Location: ${lesson.location}`:'',lesson.room?`Room: ${lesson.room}`:''].filter(Boolean).join('\n');
    const text={
      reminder:`This is a reminder about ${name}'s upcoming lesson.\n\n${details}\n\nPlease arrive a few minutes before the lesson. We look forward to seeing you!`,
      confirmation:`Please confirm whether ${name} can attend the lesson below.\n\n${details}\n\nThank you!`,
      attendance:`We are checking on ${name}'s attendance for the lesson below.\n\n${details}\n\nPlease let us know whether you are on your way or unable to attend. Thank you!`,
      reschedule:`We would like to discuss rescheduling the lesson below.\n\n${details}\n\nPlease reply with your availability. A new time will be confirmed separately. Thank you!`,
      followup:`We are following up about ${name}'s lesson.\n\n${details}\n\nPlease let us know if you have any questions or would like to discuss the next steps. Thank you!`
    }[kind];
    return text?`${greeting}\n\n${text}\n\nH-Music & Art`:'';
  }
  const api={options,build};
  if(typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.HMusicParentTemplates=api;
})(typeof window !== 'undefined'?window:this);
