import React, { useState } from 'react';
import '../styles/SwarmDesign.css'; // Import the provided CSS file


const DroneShowDesign = () => {
  const [description, setDescription] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);

  const handleFileInput = (e) => {
    const file = e.target.files[0];
    setSelectedFile(file);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Handle file upload and processing here
  };

  return (
    <div className="swarm-design-container">
      <form onSubmit={handleSubmit}>
        <label htmlFor="description">Description:</label>
        <textarea
          id="description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <label htmlFor="file-upload">Upload a zip file:</label>
        <input
          id="file-upload"
          type="file"
          accept=".zip"
          onChange={handleFileInput}
        />
        <button type="submit">Submit</button>
      </form>
    </div>
  );
};

export default DroneShowDesign;