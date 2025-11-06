package multitenant

import (
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"
)

// GET /api/repositories
// Build-safe implementation that discovers repos by scanning:
// 1) Local filesystem (if STORAGE=local) under STORAGE_LOCAL_ROOTDIR
//    - detects repos that have either <repo>/charts/*.tgz or <repo>/*.tgz
// 2) Fallback: generic storage object listing, extracting "<repo>/charts/<file>"
func (s *MultiTenantServer) listRepositoriesHandler(c *gin.Context) {
	if !s.allowListRepos() {
		c.JSON(http.StatusForbidden, gin.H{"error": "listing repositories is disabled"})
		return
	}

	// Try local FS first (works for your current setup)
	if names, ok := s.discoverReposLocalFS(); ok {
		c.JSON(http.StatusOK, names)
		return
	}

	// Fallback to generic storage scan
	names, err := s.discoverReposFromStorage("")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, names)
}

// Optional route declared in routes.go; return 403 to avoid engine deps.
func (s *MultiTenantServer) listAllChartsAcrossReposHandler(c *gin.Context) {
	c.JSON(http.StatusForbidden, gin.H{"error": "charts-all is disabled"})
}

// discoverReposLocalFS scans STORAGE_LOCAL_ROOTDIR for repos.
// It returns (names, true) if it could read the local root; otherwise (nil, false).
func (s *MultiTenantServer) discoverReposLocalFS() ([]string, bool) {
	root := os.Getenv("STORAGE_LOCAL_ROOTDIR")
	if root == "" {
		return nil, false
	}
	fi, err := os.Stat(root)
	if err != nil || !fi.IsDir() {
		return nil, false
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, false
	}

	set := make(map[string]struct{}, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		repo := e.Name()
		// Accept if we find tgz under <repo>/charts or directly under <repo>
		globs := []string{
			filepath.Join(root, repo, "charts", "*.tgz"),
			filepath.Join(root, repo, "*.tgz"),
		}
		for _, g := range globs {
			matches, _ := filepath.Glob(g)
			if len(matches) > 0 {
				set[repo] = struct{}{}
				break
			}
		}
	}

	if len(set) == 0 {
		return nil, false
	}
	names := make([]string, 0, len(set))
	for k := range set {
		names = append(names, k)
	}
	sort.Strings(names)
	return names, true
}

// discoverReposFromStorage enumerates objects and extracts repo names by:
// 1) Prefer detecting "<repo>/charts/<file>" → repo = prefix before "/charts/"
// 2) Fallback to first path segment
func (s *MultiTenantServer) discoverReposFromStorage(prefix string) ([]string, error) {
	objs, err := s.StorageBackend.ListObjects(prefix)
	if err != nil {
		return nil, err
	}

	set := make(map[string]struct{}, 64)
	for _, o := range objs {
		p := strings.TrimLeft(o.Path, "/")
		if p == "" {
			continue
		}

		// Prefer the explicit charts layout prefix (works for any nesting depth)
		if idx := strings.Index(p, "/charts/"); idx > 0 {
			repo := p[:idx]
			if repo != "" {
				set[repo] = struct{}{}
			}
			continue
		}

		// Fallback: first path segment
		if i := strings.IndexByte(p, '/'); i > 0 {
			set[p[:i]] = struct{}{}
		}
	}

	names := make([]string, 0, len(set))
	for k := range set {
		names = append(names, k)
	}
	sort.Strings(names)
	return names, nil
}

// Feature flags (simple stubs to avoid extra dependencies)
func (s *MultiTenantServer) allowListRepos() bool    { return true }
func (s *MultiTenantServer) allowChartsAll() bool    { return false }
func (s *MultiTenantServer) repoListMaxObjects() int { return 0 }
