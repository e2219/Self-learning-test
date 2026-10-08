import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { LibraryApp } from './LibraryApp';
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LibraryApp />
    </BrowserRouter>
  </React.StrictMode>,
);
