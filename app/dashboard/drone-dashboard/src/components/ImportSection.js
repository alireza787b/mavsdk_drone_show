// src/components/ImportSection.js
import React, { useState } from 'react';
import { getBackendURL } from '../utilities/utilities';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import '../styles/ImportSection.css';
import { 
  Button, 
  CircularProgress, 
  Typography, 
  Box, 
  Paper, 
  List, 
  ListItem, 
  ListItemText, 
  Link 
} from '@mui/material';

const ImportSection = ({ setUploadCount }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) {
      toast.warn('No file selected. Please choose a file.');
      return;
    }
    if (!file.name.endsWith('.zip')) {
      toast.error('Invalid file type. Please select a ZIP file.');
      return;
    }
    setSelectedFile(file);
  };

  const uploadFile = () => {
    if (!selectedFile) {
      toast.warn('Please select a file to upload.');
      return;
    }

    const formData = new FormData();
    formData.append('file', selectedFile);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getBackendURL()}/import-show`);

    xhr.onload = () => {
      setIsUploading(false);
      if (xhr.status === 200) {
        try {
          const result = JSON.parse(xhr.responseText);
          if (result.success) {
            toast.success('File uploaded and processed successfully!');
            setUploadCount((prev) => prev + 1);
            setSelectedFile(null);
          } else {
            toast.error(result.error || 'Unknown error during file upload.');
          }
        } catch (error) {
          console.error('Error parsing response:', error);
          toast.error('Invalid server response.');
        }
      } else {
        toast.error('Network error. Please try again.');
      }
    };

    xhr.onerror = () => {
      setIsUploading(false);
      toast.error('Network error. Please try again.');
    };

    setIsUploading(true);
    xhr.send(formData);
  };

  return (
    <Box className="import-section">
      <Typography variant="h5" sx={{ color: '#0056b3', mb: 2 }}>
        Import Drone Show
      </Typography>

      <Box className="intro-section" sx={{ mb: 2 }}>
        <Typography variant="body1" paragraph>
          Welcome to the Drone Show Import Utility of our Swarm Dashboard. This tool
          streamlines the entire workflow for your drone shows. Here's what you can do:
        </Typography>
        
        <List dense>
          <ListItem>
            <ListItemText primary="Upload: ZIP files exported from SkyBrush with one click." />
          </ListItem>
          <ListItem>
            <ListItemText primary="Process: Automatically adapts for drone show compatibility." />
          </ListItem>
          <ListItem>
            <ListItemText primary="Visualize: Generates plots for your drone paths automatically." />
          </ListItem>
          <ListItem>
            <ListItemText primary="Update: Mission configuration is automatically updated." />
          </ListItem>
          <ListItem>
            <ListItemText primary="Access: Retrieve processed files from shapes/swarm directory." />
          </ListItem>
        </List>

        <Typography variant="body1" paragraph>
          SkyBrush is a plugin compatible with Blender and 3D Max, designed for
          creating drone show animations. Learn how to create stunning animations in our{' '}
          <Link 
            href="https://youtu.be/wctmCIzpMpY" 
            target="_blank" 
            rel="noreferrer"
            color="primary" 
            underline="hover"
          >
            YouTube tutorial
          </Link>.
        </Typography>

        <Typography variant="body1">
          For advanced users needing more control, you can directly execute the 
          <code> process_formation.py </code> Python script. The files will be exported 
          to the <code> shapes/swarm </code> directory.
        </Typography>
      </Box>

      {/* File Upload Section */}
      <Paper sx={{ p: 2 }}>
        <Box className="file-upload" sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Button variant="outlined" component="label">
            {selectedFile ? selectedFile.name : 'Choose ZIP File'}
            <input
              type="file"
              accept=".zip"
              onChange={handleFileChange}
              hidden
            />
          </Button>
          
          <Button 
            variant="contained" 
            onClick={uploadFile} 
            disabled={!selectedFile || isUploading}
          >
            {isUploading ? (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={20} color="inherit" />
                <span>Uploading...</span>
              </Box>
            ) : (
              'Upload'
            )}
          </Button>
        </Box>
      </Paper>
    </Box>
  );
};

export default ImportSection;
