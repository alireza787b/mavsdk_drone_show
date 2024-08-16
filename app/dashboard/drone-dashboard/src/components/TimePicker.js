import React from 'react';

const TimePicker = ({ selectedTime, onTimePickerChange }) => (
  <div className="time-picker">
    <label htmlFor="time-picker">Select Time:</label>
    <input
      type="time"
      id="time-picker"
      value={selectedTime}
      onChange={(e) => onTimePickerChange(e.target.value)}
      step="1"
    />
  </div>
);

export default TimePicker;
