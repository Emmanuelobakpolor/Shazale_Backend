from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
from django.conf import settings
import logging
import time

from .models import AudioSearch, SearchResult

logger = logging.getLogger(__name__)

class UploadView(APIView):
    def post(self, request, format=None):
        logger.info("UploadView POST called")
        file = request.FILES.get('file')
        if not file:
            logger.error("No file uploaded")
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"Received file: {file.name}, content_type: {file.content_type}, size: {file.size}")

        # Validate file type
        if not file.content_type.startswith('audio/'):
            logger.error("Uploaded file is not an audio file")
            return Response({"error": "File must be an audio file"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate file size (max 10MB)
        if file.size > 10 * 1024 * 1024:
            logger.error("Uploaded file size exceeds 10MB")
            return Response({"error": "File size must be less than 10MB"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            logger.info("Creating AudioSearch instance")
            audio_search = AudioSearch.objects.create(audio_file=file)
            start_time = time.time()

            # Real audio processing using AudD.io API
            recognition_result = self._process_audio(file)
            processing_time = time.time() - start_time

            if not recognition_result or 'result' not in recognition_result or recognition_result['result'] is None:
                logger.error("Audio recognition failed or no result found")
                return Response({"error": "Audio recognition failed or no result found"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Use YouTube API to get video details for recognized tracks
            youtube_results = self._get_youtube_results(recognition_result['result'])

            # Use TMDB API to get streaming availability
            tmdb_results = self._get_tmdb_streaming_availability(recognition_result['result'])

            # Combine results
            combined_results = self._combine_results(youtube_results, tmdb_results)

            # Save results to database
            search_results = []
            for result_data in combined_results:
                # Skip results with missing or empty 'url' to avoid NOT NULL constraint error
                if not result_data.get('url'):
                    logger.warning(f"Skipping SearchResult creation due to missing url: {result_data.get('title', 'No Title')}")
                    continue
                result = SearchResult.objects.create(**result_data)
                search_results.append(result)
                audio_search.search_results.add(result)

            # Update processing status
            audio_search.is_processed = True
            audio_search.processing_time = processing_time
            audio_search.save()

            logger.info("Returning response with search results")
            response_data = {
                "search_id": audio_search.id,
                "processing_time": round(processing_time, 2),
                "results": [
                    {
                        "id": result.id,
                        "title": result.title,
                        "platform": result.platform,
                        "url": result.url,
                        "thumbnail_url": result.thumbnail_url,
                        "duration": result.duration,
                        "channel_name": result.channel_name,
                        "view_count": result.view_count,
                        "netflix_url": result.netflix_url,
                        "prime_url": result.prime_url,
                        "hulu_url": result.hulu_url,
                        "disney_url": result.disney_url,
                    }
                    for result in search_results
                ]
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Processing failed: {str(e)}", exc_info=True)
            return Response({"error": f"Processing failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_audio(self, file):
        """Process audio using AudD.io API"""
        url = "https://api.audd.io/"
        try:
            file.seek(0)
            files = {'file': file}
            data = {
                'api_token': settings.AUDD_API_TOKEN,
                'return': 'timecode,apple_music,spotify',
            }
            response = requests.post(url, files=files, data=data)
            logger.info(f"AudD.io API response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"AudD.io API response: {data}")
                if data.get('status') == 'success' and 'result' in data:
                    return data
                else:
                    logger.error(f"AudD.io API returned success but no result: {data}")
                    return None
            else:
                logger.error(f"AudD.io API request failed with status {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error processing audio with AudD.io: {str(e)}")
            return None

    def _get_youtube_results(self, audd_result):
        """Use YouTube Data API to get video details for recognized tracks"""
        youtube_api_key = settings.YOUTUBE_API_KEY
        base_url = "https://www.googleapis.com/youtube/v3/search"
        results = []
        default_thumbnail = "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"

        title = audd_result.get('title', '')
        artist = audd_result.get('artist', '')
        query = f"{title} {artist}".strip()

        if not query:
            logger.warning("No valid query for YouTube search")
            return results

        params = {
            'part': 'snippet',
            'q': query,
            'key': youtube_api_key,
            'maxResults': 5,
            'type': 'video',
        }

        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            for item in data.get('items', []):
                video_id = item['id']['videoId']
                snippet = item['snippet']
                search_query = query.replace(' ', '+')
                results.append({
                    'title': snippet.get('title', ''),
                    'platform': 'YouTube',
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'thumbnail_url': snippet.get('thumbnails', {}).get('high', {}).get('url', default_thumbnail),
                    'duration': '',
                    'channel_name': snippet.get('channelTitle', ''),
                    'view_count': '',
                    'netflix_url': f"https://www.netflix.com/search?q={search_query}",
                    'prime_url': f"https://www.amazon.com/s?k={search_query}&i=instant-video",
                    'hulu_url': f"https://www.hulu.com/search?q={search_query}",
                    'disney_url': f"https://www.disneyplus.com/search?q={search_query}",
                })
        except requests.RequestException as e:
            logger.error(f"YouTube API request failed: {str(e)}")

        return results

    def _get_tmdb_streaming_availability(self, audd_result):
        """Use TMDB API to get streaming availability for recognized content"""
        tmdb_api_key = settings.TMDB_API_KEY
        base_url = "https://api.themoviedb.org/3/search/multi"
        results = []
        default_thumbnail = "https://via.placeholder.com/500x750/cccccc/000000?text=No+Image"

        title = audd_result.get('title', '')
        if not title:
            logger.warning("No title provided in AudD result")
            return results

        params = {
            'api_key': tmdb_api_key,
            'query': title,
            'include_adult': 'false',
        }

        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            for item in data.get('results', []):
                media_type = item.get('media_type')
                if media_type not in ['movie', 'tv']:
                    continue

                tmdb_id = item.get('id')
                providers = self._get_providers(tmdb_id, media_type)
                thumbnail = (
                    f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}"
                    if item.get('poster_path')
                    else default_thumbnail
                )

                movie_title = item.get('title') or item.get('name', '')
                movie_query = movie_title.replace(' ', '+')
                results.append({
                    'title': movie_title,
                    'platform': 'TMDB',
                    'url': providers.get('tmdb_watch', ''),
                    'thumbnail_url': thumbnail,
                    'duration': '',
                    'channel_name': '',
                    'view_count': '',
                    'netflix_url': f"https://www.netflix.com/search?q={movie_query}",
                    'prime_url': f"https://www.amazon.com/s?k={movie_query}&i=instant-video",
                    'hulu_url': f"https://www.hulu.com/search?q={movie_query}",
                    'disney_url': f"https://www.disneyplus.com/search?q={movie_query}",
                })
        except requests.RequestException as e:
            logger.error(f"TMDB API request failed: {str(e)}")

        return results

    def _get_providers(self, tmdb_id, media_type, region="US"):
        """Get streaming providers for a TMDB movie or TV show with multi-region support"""
        tmdb_api_key = settings.TMDB_API_KEY
        base_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers"
        params = {'api_key': tmdb_api_key, 'region': region}
        fallback_regions = [region, "US", "GB", "IN"]
        provider_urls = {
            'netflix': None,
            'prime': None,
            'hulu': None,
            'disney': None,
            'tmdb_watch': None,
        }

        for reg in fallback_regions:
            try:
                params['region'] = reg
                response = requests.get(base_url, params=params)
                response.raise_for_status()
                data = response.json()
                results = data.get('results', {})

                if reg not in results:
                    continue

                region_data = results[reg]
                provider_urls['tmdb_watch'] = region_data.get("link")

                flatrate = region_data.get('flatrate', [])
                for provider in flatrate:
                    provider_name = provider.get('provider_name', '').lower()
                    if 'netflix' in provider_name and not provider_urls['netflix']:
                        provider_urls['netflix'] = provider_urls['tmdb_watch']
                    elif ('prime' in provider_name or 'amazon' in provider_name) and not provider_urls['prime']:
                        provider_urls['prime'] = provider_urls['tmdb_watch']
                    elif 'hulu' in provider_name and not provider_urls['hulu']:
                        provider_urls['hulu'] = provider_urls['tmdb_watch']
                    elif 'disney' in provider_name and not provider_urls['disney']:
                        provider_urls['disney'] = provider_urls['tmdb_watch']

                if any(url for key, url in provider_urls.items() if key != 'tmdb_watch'):
                    break
            except requests.RequestException as e:
                logger.error(f"Error fetching TMDB providers for {media_type} {tmdb_id} in region {reg}: {str(e)}")
                continue

        return provider_urls

    def _combine_results(self, youtube_results, tmdb_results):
        """Combine YouTube and TMDB results intelligently, ensuring thumbnails"""
        default_thumbnail = "https://via.placeholder.com/500x750/cccccc/000000?text=No+Image"
        combined = []

        try:
            if not isinstance(youtube_results, list) or not isinstance(tmdb_results, list):
                logger.error("Invalid input types for combining results")
                return youtube_results if isinstance(youtube_results, list) else []

            for result in youtube_results:
                if not result.get('thumbnail_url') or result['thumbnail_url'].endswith("None"):
                    result['thumbnail_url'] = default_thumbnail
                combined.append(result)

            youtube_titles = {r.get('title', '').lower().strip() for r in youtube_results
                            if isinstance(r, dict) and r.get('title')}

            for tmdb_res in tmdb_results:
                if not isinstance(tmdb_res, dict) or not tmdb_res.get('title'):
                    continue
                tmdb_title = tmdb_res['title'].lower().strip()
                if tmdb_title not in youtube_titles:
                    if not tmdb_res.get('thumbnail_url') or tmdb_res['thumbnail_url'].endswith("None"):
                        tmdb_res['thumbnail_url'] = default_thumbnail
                    combined.append(tmdb_res)
                    youtube_titles.add(tmdb_title)

            return combined
        except Exception as e:
            logger.error(f"Error combining results: {str(e)}")
            return youtube_results if isinstance(youtube_results, list) else []