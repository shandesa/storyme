import React, { useState } from 'react';
import axios from 'axios';
import { useLocation, useNavigate } from 'react-router-dom';

export default function RegisterPage() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');

  const register = async () => {
    await axios.post('/api/auth/register', {
      mobile: state.mobile,
      password
    });
    navigate('/home');
  };

  return (
    <div className="p-6 max-w-md mx-auto">
      <h2 className="text-xl font-bold mb-4">Create Account</h2>
      <p className="mb-2 text-sm">Looks like you're new here. Let’s get you started.</p>
      <input
        type="password"
        className="border p-2 w-full mb-2"
        placeholder="Create Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button className="bg-green-500 text-white p-2 w-full" onClick={register}>Create Account</button>
    </div>
  );
}
