package com.example.auth.dto;

public class LoginResponse {
    private String token;
    private long expiresIn;

    public LoginResponse(String token, long expiresIn) {
        this.token = token;
        this.expiresIn = expiresIn;
    }

    public String getToken() { return token; }
    public long getExpiresIn() { return expiresIn; }
}
