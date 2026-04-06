import React, { useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

export default function LoginPage() {
  const [mobile, setMobile] = useState('');
  const [password, setPassword] = useState('');
  const [mode, setMode] = useState('otp');
  const navigate = useNavigate();

  const sendOtp = async () => {
    await axios.post('/api/auth/send-otp', { mobile });
    navigate('/otp', { state: { mobile } });
  };

  const loginPassword = async () => {
    try {
      const res = await axios.post('/api/auth/login-password', { mobile, password });
      if (res.data.status === 'LOGIN_SUCCESS') {
        navigate('/home');
      }
    } catch {
      alert('Login failed');
    }
  };

  return (
    <div className="p-6 max-w-md mx-auto">
      <h2 className="text-xl font-bold mb-4">Login</h2>

      <select className="mb-2">
        <option>India (+91)</option>
      </select>

      <input
        className="border p-2 w-full mb-2"
        placeholder="Mobile Number"
        value={mobile}
        onChange={(e) => setMobile(e.target.value.replace(/\D/g, ''))}
      />

      {mode === 'password' && (
        <input
          type="password"
          className="border p-2 w-full mb-2"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      )}

      {mode === 'otp' ? (
        <button className="bg-blue-500 text-white p-2 w-full" onClick={sendOtp}>Send OTP</button>
      ) : (
        <button className="bg-green-500 text-white p-2 w-full" onClick={loginPassword}>Login</button>
      )}

      <div className="mt-4 text-sm">
        <span onClick={() => setMode(mode === 'otp' ? 'password' : 'otp')} className="text-blue-500 cursor-pointer">
          Switch to {mode === 'otp' ? 'Password' : 'OTP'} Login
        </span>
      </div>
    </div>
  );
}
