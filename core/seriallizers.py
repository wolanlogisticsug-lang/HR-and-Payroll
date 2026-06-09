# Wolan HR - Communications Serializers
from rest_framework import serializers


class NotificationSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    message = serializers.CharField()
    recipient = serializers.CharField()
    is_read = serializers.BooleanField(default=False)
    created_at = serializers.DateTimeField(read_only=True)


class EmailSerializer(serializers.Serializer):
    to = serializers.EmailField()
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField()