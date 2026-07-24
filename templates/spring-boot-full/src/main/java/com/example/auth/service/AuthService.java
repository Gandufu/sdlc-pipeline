package com.example.auth.service;

import com.example.auth.dto.LoginRequest;
import com.example.auth.dto.LoginResponse;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
    public LoginResponse login(LoginRequest request) {
        return new LoginResponse("scaffold-token-" + request.getUsername(), 3600);
    }
}
