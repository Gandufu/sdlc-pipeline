package com.example.common;

public record Result<T>(boolean success, T data) {
    public static <T> Result<T> ok(T data) {
        return new Result<>(true, data);
    }
}
