from rest_framework import serializers


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    detail = serializers.CharField(required=False)


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    version = serializers.CharField()
    database = serializers.BooleanField()
    server_time = serializers.DateTimeField()
