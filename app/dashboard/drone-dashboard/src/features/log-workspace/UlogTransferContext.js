import { createContext, useContext } from 'react';

export const UlogTransferContext = createContext(null);

export function useUlogTransferContext() {
  return useContext(UlogTransferContext);
}
