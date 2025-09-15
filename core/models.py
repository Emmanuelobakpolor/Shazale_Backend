from django.db import models
from django.utils import timezone

class SearchResult(models.Model):
    """Model to store individual search results"""
    title = models.CharField(max_length=500)
    platform = models.CharField(max_length=50, default='YouTube')
    url = models.URLField()
    thumbnail_url = models.URLField(blank=True, null=True)
    duration = models.CharField(max_length=20, blank=True, null=True)
    channel_name = models.CharField(max_length=200, blank=True, null=True)
    view_count = models.CharField(max_length=50, blank=True, null=True)
    # Streaming platform availability
    netflix_url = models.URLField(blank=True, null=True)
    prime_url = models.URLField(blank=True, null=True)
    hulu_url = models.URLField(blank=True, null=True)
    disney_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.platform}"


class AudioSearch(models.Model):
    """Model to store audio search requests and their results"""
    audio_file = models.FileField(upload_to='audio_searches/')
    search_results = models.ManyToManyField(SearchResult, related_name='searches')
    is_processed = models.BooleanField(default=False)
    processing_time = models.FloatField(blank=True, null=True)  # in seconds
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Audio Search {self.id} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
