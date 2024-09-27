// src/components/ConfirmModal.js
import React from 'react';
import styled from 'styled-components';

const ModalOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 2000;
`;

const ModalContent = styled.div`
  background-color: #ffffff;
  padding: 25px;
  border-radius: 8px;
  width: 90%;
  max-width: 400px;
  text-align: center;
`;

const ModalHeader = styled.h3`
  margin-bottom: 15px;
  color: #333333;
`;

const ModalMessage = styled.p`
  margin-bottom: 25px;
  color: #555555;
`;

const ModalActions = styled.div`
  display: flex;
  justify-content: space-around;
`;

const ConfirmButton = styled.button`
  background-color: #4CAF50;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.3s;
  
  &:hover {
    background-color: #45A049;
  }
`;

const CancelButton = styled.button`
  background-color: #F44336;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.3s;
  
  &:hover {
    background-color: #D32F2F;
  }
`;

const ConfirmModal = ({ isOpen, title, message, onConfirm, onCancel }) => {
  if (!isOpen) return null;

  return (
    <ModalOverlay>
      <ModalContent>
        <ModalHeader>{title}</ModalHeader>
        <ModalMessage>{message}</ModalMessage>
        <ModalActions>
          <ConfirmButton onClick={onConfirm}>Yes</ConfirmButton>
          <CancelButton onClick={onCancel}>No</CancelButton>
        </ModalActions>
      </ModalContent>
    </ModalOverlay>
  );
};

export default ConfirmModal;
