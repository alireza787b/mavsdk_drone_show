// src/components/FileUpload.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import '../styles/FileUpload.css';

const FileUpload = ({ onFileSelect, selectedFile }) => {
  const [dragging, setDragging] = useState(false);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      onFileSelect(file);
    }
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const files = [...e.dataTransfer.files];
    if (files.length > 0) {
      onFileSelect(files[0]);
    }
  };

  return (
    <div
      className={`drop-zone ${dragging ? 'dragging' : ''}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
    >
      <input type="file" accept=".zip" onChange={handleFileChange} />
      <p>
        {selectedFile ? (
          <>
            Selected File: <strong>{selectedFile.name}</strong>
          </>
        ) : (
          'Drag & drop a ZIP file here, or click to select one'
        )}
      </p>
    </div>
  );
};

FileUpload.propTypes = {
  onFileSelect: PropTypes.func.isRequired,
  selectedFile: PropTypes.object,
};

export default FileUpload;
