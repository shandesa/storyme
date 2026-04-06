import React, { useState } from 'react';
import axios from 'axios';
import { useLocation, useNavigate } from 'react-router-dom';

export default function OtpPage() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const [otp, setOtp] = useState('');

  const verifyOtp = async () => {
    const res = await axios.post('/api/auth/verify-otp', {
      mobile: state.mobile,
      otp
    });

    if (res.data.status === 'NEW_USER') {
      navigate('/register', { state: { mobile: state.mobile } });
    } else {
      navigate('/home');
    }
  };

  return (
    <div className="p-6 max-w-md mx-auto">
      <h2 className="text-xl font-bold mb-4">Enter OTP</h2>
      <input
        className="border p-2 w-full mb-2"
        placeholder="OTP"
        value={otp}
        onChange={(e) => setOtp(e.target.value)}
      />
      <button className="bg-blue-500 text-white p-2 w-full" onClick={verifyOtp}>Verify</button>
    </div>
  );
}
