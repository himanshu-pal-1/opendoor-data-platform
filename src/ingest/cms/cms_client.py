"""CMS data download client.

This module handles downloading Medicare physician payment data from CMS
public datasets, including Provider Utilization and Payment Data.
"""

import os
import zipfile
from pathlib import Path
from typing import Optional

import httpx
import structlog
from tqdm import tqdm

logger = structlog.get_logger()

# CMS data URLs
CMS_DATA_BASE_URL = "https://data.cms.gov/provider-data"
CMS_PHYSICIAN_COMPARE_URL = (
    "https://data.cms.gov/provider-data/dataset/mj5m-pzi6"  # Physician Compare
)


class CMSDownloadError(Exception):
    """Raised when CMS data download fails."""

    pass


class CMSClient:
    """Client for downloading CMS Medicare payment data.

    This client handles downloading various CMS public datasets including
    Medicare Physician & Other Practitioners payment data, Physician Compare,
    and other provider datasets.

    Attributes:
        download_dir: Directory to store downloaded files.
        timeout: Request timeout in seconds.
        max_retries: Maximum download retry attempts.

    Example:
        >>> client = CMSClient(download_dir="/data/cms")
        >>> file_path = client.download_physician_payments(year=2022)
        >>> print(f"Downloaded to: {file_path}")
    """

    def __init__(
        self,
        download_dir: str = "./data/cms",
        timeout: int = 300,
        max_retries: int = 3,
    ):
        """Initialize CMS client.

        Args:
            download_dir: Directory to store downloaded files.
            timeout: Request timeout in seconds.
            max_retries: Maximum download retry attempts.
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self._api_key = os.getenv("CMS_API_KEY")

    def _get_headers(self) -> dict:
        """Get request headers including API key if available."""
        headers = {
            "User-Agent": "OpenDoor-Data-Platform/1.0",
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def download_file(
        self,
        url: str,
        destination: Path,
        show_progress: bool = True,
    ) -> Path:
        """Download a file from URL with progress tracking.

        Args:
            url: URL to download.
            destination: Local file path to save to.
            show_progress: Whether to show progress bar.

        Returns:
            Path to downloaded file.

        Raises:
            CMSDownloadError: If download fails after retries.
        """
        logger.info("starting_cms_download", url=url, destination=str(destination))

        for attempt in range(self.max_retries):
            try:
                with httpx.stream(
                    "GET",
                    url,
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers=self._get_headers(),
                ) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))

                    with open(destination, "wb") as f:
                        if show_progress and total_size > 0:
                            with tqdm(
                                total=total_size,
                                unit="B",
                                unit_scale=True,
                                desc="Downloading CMS Data",
                            ) as pbar:
                                for chunk in response.iter_bytes(chunk_size=8192):
                                    f.write(chunk)
                                    pbar.update(len(chunk))
                        else:
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)

                logger.info(
                    "cms_download_complete",
                    destination=str(destination),
                    size_bytes=os.path.getsize(destination),
                )
                return destination

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "cms_download_http_error",
                    attempt=attempt + 1,
                    status_code=e.response.status_code,
                )
                if attempt == self.max_retries - 1:
                    raise CMSDownloadError(
                        f"HTTP error after {self.max_retries} attempts: {e}"
                    )

            except httpx.RequestError as e:
                logger.warning(
                    "cms_download_request_error",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt == self.max_retries - 1:
                    raise CMSDownloadError(
                        f"Request error after {self.max_retries} attempts: {e}"
                    )

        raise CMSDownloadError("Download failed after all retries")

    def extract_zip(self, zip_path: Path, extract_dir: Optional[Path] = None) -> Path:
        """Extract ZIP file.

        Args:
            zip_path: Path to ZIP file.
            extract_dir: Directory to extract to (defaults to same as ZIP).

        Returns:
            Path to extraction directory.
        """
        if extract_dir is None:
            extract_dir = zip_path.parent / zip_path.stem

        extract_dir.mkdir(parents=True, exist_ok=True)

        logger.info("extracting_zip", zip_path=str(zip_path), extract_dir=str(extract_dir))

        with zipfile.ZipFile(zip_path, "r") as zf:
            total_size = sum(info.file_size for info in zf.infolist())

            with tqdm(total=total_size, unit="B", unit_scale=True, desc="Extracting") as pbar:
                for member in zf.infolist():
                    zf.extract(member, extract_dir)
                    pbar.update(member.file_size)

        logger.info("extraction_complete", extract_dir=str(extract_dir))
        return extract_dir

    def get_physician_payments_url(self, year: int) -> str:
        """Get the URL for Medicare Physician Payment data.

        Args:
            year: Data year.

        Returns:
            Download URL for the dataset.
        """
        # Medicare Physician & Other Practitioners Payment Data
        # This is a placeholder - actual URLs vary by year
        return f"https://data.cms.gov/provider-data/api/1/datastore/query/mj5m-pzi6?year={year}"

    def download_physician_payments(
        self,
        year: int,
        extract: bool = True,
    ) -> Path:
        """Download Medicare Physician Payment data for a specific year.

        Args:
            year: Data year (e.g., 2022).
            extract: Whether to extract ZIP file.

        Returns:
            Path to data file.
        """
        filename = f"cms_physician_payments_{year}.csv"
        file_path = self.download_dir / filename

        if file_path.exists():
            logger.info("using_cached_cms_file", path=str(file_path))
            return file_path

        # For demonstration - actual implementation would use CMS API
        url = self.get_physician_payments_url(year)
        logger.info("downloading_physician_payments", year=year, url=url)

        # Download the file
        self.download_file(url, file_path)

        return file_path

    def download_physician_compare(self) -> Path:
        """Download Physician Compare data.

        Returns:
            Path to Physician Compare CSV file.
        """
        filename = "physician_compare.csv"
        file_path = self.download_dir / filename

        if file_path.exists():
            logger.info("using_cached_file", path=str(file_path))
            return file_path

        # Physician Compare download URL
        url = (
            "https://data.cms.gov/provider-data/api/1/datastore/query/"
            "mj5m-pzi6/0/download?format=csv"
        )

        self.download_file(url, file_path)
        return file_path

    def list_available_datasets(self) -> list[dict]:
        """List available CMS provider datasets.

        Returns:
            List of dataset information dictionaries.
        """
        datasets = [
            {
                "name": "Medicare Physician & Other Practitioners",
                "description": "Medicare utilization and payment data by provider",
                "years": list(range(2013, 2024)),
                "type": "payment",
            },
            {
                "name": "Physician Compare",
                "description": "Physician demographic and practice information",
                "years": ["current"],
                "type": "demographic",
            },
            {
                "name": "Medicare Provider Utilization",
                "description": "Aggregate utilization data by HCPCS code",
                "years": list(range(2013, 2024)),
                "type": "utilization",
            },
        ]
        return datasets
