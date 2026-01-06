"""NPPES data download client.

This module handles downloading NPPES (National Plan and Provider Enumeration
System) data from CMS. The NPPES NPI Registry contains information about
all healthcare providers with an NPI.
"""

import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import structlog
from tqdm import tqdm

logger = structlog.get_logger()

# Default NPPES download URL pattern
NPPES_BASE_URL = "https://download.cms.gov/nppes"
NPPES_FULL_FILE_PATTERN = "NPPES_Data_Dissemination_{month}_{year}.zip"


class NPPESDownloadError(Exception):
    """Raised when NPPES data download fails."""

    pass


class NPPESClient:
    """Client for downloading NPPES NPI Registry data.

    This client handles downloading the monthly NPPES data dissemination
    files from CMS, including handling large file downloads, retries,
    and ZIP extraction.

    Attributes:
        download_dir: Directory to store downloaded files.
        timeout: Request timeout in seconds.
        max_retries: Maximum download retry attempts.

    Example:
        >>> client = NPPESClient(download_dir="/data/nppes")
        >>> file_path = client.download_latest()
        >>> print(f"Downloaded to: {file_path}")
    """

    def __init__(
        self,
        download_dir: str = "./data/nppes",
        timeout: int = 300,
        max_retries: int = 3,
    ):
        """Initialize NPPES client.

        Args:
            download_dir: Directory to store downloaded files.
            timeout: Request timeout in seconds.
            max_retries: Maximum download retry attempts.
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries

    def _get_download_url(self, year: int, month: str) -> str:
        """Construct the NPPES download URL for a specific month.

        Args:
            year: Four-digit year.
            month: Full month name (e.g., "January").

        Returns:
            Full download URL.
        """
        filename = NPPES_FULL_FILE_PATTERN.format(month=month, year=year)
        return f"{NPPES_BASE_URL}/{filename}"

    def _get_latest_month(self) -> tuple[int, str]:
        """Get the most recent available month for NPPES data.

        Returns:
            Tuple of (year, month_name).
        """
        now = datetime.now()
        # NPPES data is typically released mid-month for previous month
        if now.day < 15:
            # Use data from 2 months ago to be safe
            if now.month <= 2:
                year = now.year - 1
                month_num = now.month + 10  # Handle year boundary
            else:
                year = now.year
                month_num = now.month - 2
        else:
            # Use data from previous month
            if now.month == 1:
                year = now.year - 1
                month_num = 12
            else:
                year = now.year
                month_num = now.month - 1

        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        return year, months[month_num - 1]

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
            NPPESDownloadError: If download fails after retries.
        """
        logger.info("starting_download", url=url, destination=str(destination))

        for attempt in range(self.max_retries):
            try:
                with httpx.stream(
                    "GET", url, timeout=self.timeout, follow_redirects=True
                ) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get("content-length", 0))

                    with open(destination, "wb") as f:
                        if show_progress and total_size > 0:
                            with tqdm(
                                total=total_size,
                                unit="B",
                                unit_scale=True,
                                desc="Downloading NPPES",
                            ) as pbar:
                                for chunk in response.iter_bytes(chunk_size=8192):
                                    f.write(chunk)
                                    pbar.update(len(chunk))
                        else:
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)

                logger.info(
                    "download_complete",
                    destination=str(destination),
                    size_bytes=os.path.getsize(destination),
                )
                return destination

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "download_http_error",
                    attempt=attempt + 1,
                    status_code=e.response.status_code,
                    url=url,
                )
                if attempt == self.max_retries - 1:
                    raise NPPESDownloadError(
                        f"HTTP error after {self.max_retries} attempts: {e}"
                    )

            except httpx.RequestError as e:
                logger.warning(
                    "download_request_error",
                    attempt=attempt + 1,
                    error=str(e),
                    url=url,
                )
                if attempt == self.max_retries - 1:
                    raise NPPESDownloadError(
                        f"Request error after {self.max_retries} attempts: {e}"
                    )

        raise NPPESDownloadError("Download failed after all retries")

    def extract_zip(self, zip_path: Path, extract_dir: Optional[Path] = None) -> Path:
        """Extract NPPES ZIP file.

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
            # Get total uncompressed size for progress
            total_size = sum(info.file_size for info in zf.infolist())

            with tqdm(total=total_size, unit="B", unit_scale=True, desc="Extracting") as pbar:
                for member in zf.infolist():
                    zf.extract(member, extract_dir)
                    pbar.update(member.file_size)

        logger.info("extraction_complete", extract_dir=str(extract_dir))
        return extract_dir

    def find_npi_file(self, extract_dir: Path) -> Optional[Path]:
        """Find the main NPI data file in extracted directory.

        Args:
            extract_dir: Directory containing extracted files.

        Returns:
            Path to NPI data CSV file, or None if not found.
        """
        # Look for the main NPI file (pattern: npidata_pfile_*.csv)
        for file in extract_dir.glob("npidata_pfile_*.csv"):
            logger.info("found_npi_file", file=str(file))
            return file

        # Fallback: look for any large CSV
        csv_files = list(extract_dir.glob("*.csv"))
        if csv_files:
            # Return the largest CSV file
            largest = max(csv_files, key=lambda f: f.stat().st_size)
            logger.info("found_csv_file", file=str(largest))
            return largest

        logger.warning("no_npi_file_found", extract_dir=str(extract_dir))
        return None

    def download_latest(self, extract: bool = True) -> Path:
        """Download the latest NPPES data file.

        Args:
            extract: Whether to extract the ZIP file.

        Returns:
            Path to NPI data CSV file (if extracted) or ZIP file.
        """
        year, month = self._get_latest_month()
        url = self._get_download_url(year, month)

        zip_filename = f"nppes_{year}_{month.lower()}.zip"
        zip_path = self.download_dir / zip_filename

        # Download if not already present
        if not zip_path.exists():
            self.download_file(url, zip_path)
        else:
            logger.info("using_cached_file", path=str(zip_path))

        if extract:
            extract_dir = self.extract_zip(zip_path)
            npi_file = self.find_npi_file(extract_dir)
            if npi_file:
                return npi_file
            raise NPPESDownloadError("Could not find NPI data file in extracted archive")

        return zip_path

    def download_specific(
        self, year: int, month: str, extract: bool = True
    ) -> Path:
        """Download NPPES data for a specific month.

        Args:
            year: Four-digit year.
            month: Full month name (e.g., "January").
            extract: Whether to extract the ZIP file.

        Returns:
            Path to NPI data CSV file (if extracted) or ZIP file.
        """
        url = self._get_download_url(year, month)

        zip_filename = f"nppes_{year}_{month.lower()}.zip"
        zip_path = self.download_dir / zip_filename

        if not zip_path.exists():
            self.download_file(url, zip_path)
        else:
            logger.info("using_cached_file", path=str(zip_path))

        if extract:
            extract_dir = self.extract_zip(zip_path)
            npi_file = self.find_npi_file(extract_dir)
            if npi_file:
                return npi_file
            raise NPPESDownloadError("Could not find NPI data file in extracted archive")

        return zip_path
