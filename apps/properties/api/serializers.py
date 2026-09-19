"""Properties API serializers (A2 addition to the A0 thin HTTP surface).

Added while building A2's availability search screen: no A0 endpoint lets a
client discover which properties exist, yet ``property_id`` is the first
required field of ``GET /api/availability/`` — an unusable-from-the-UI gap,
not a new capability. Mirrors ``apps.rooms.api``'s style exactly.
"""

from rest_framework import serializers

from apps.properties.models import Property


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "code", "name", "status", "currency", "timezone"]
